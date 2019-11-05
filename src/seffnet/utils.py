# -*- coding: utf-8 -*-

"""Utilities for :mod:`seffnet`."""

import datetime
import getpass
import json
import os
import random
from typing import Any, Mapping, Optional

import networkx as nx
import numpy as np
import optuna
import pandas as pd
import pybel
from bionev import pipeline
from bionev.embed_train import embedding_training
from bionev.utils import read_node_labels
from sklearn.model_selection import GroupShuffleSplit
from tqdm import tqdm

from .constants import (
    DEFAULT_CLUSTERED_CHEMICALS, DEFAULT_FULLGRAPH_PICKLE, DEFAULT_MAPPING_PATH, DEFAULT_TESTING_SET,
    DEFAULT_TRAINING_SET,
)
from .optimization import (
    deepwalk_optimization, grarep_optimization, hope_optimization, line_optimization,
    node2vec_optimization, sdne_optimization,
)


def study_to_json(study: optuna.Study, prediction_task) -> Mapping[str, Any]:
    """Serialize a study to JSON."""
    if prediction_task == 'link_prediction':
        return {
            'n_trials': len(study.trials),
            'name': study.study_name,
            'id': study.study_id,
            'prediction_task': prediction_task,
            'start': study.user_attrs['Date'],
            'seed': study.user_attrs['Seed'],
            'best': {
                'mcc': study.best_trial.user_attrs['mcc'],
                'accuracy': study.best_trial.user_attrs['accuracy'],
                'auc_roc': study.best_trial.user_attrs['auc_roc'],
                'auc_pr': study.best_trial.user_attrs['auc_pr'],
                'f1': study.best_trial.user_attrs['f1'],
                'method': study.best_trial.user_attrs['method'],
                'classifier': study.best_trial.user_attrs['classifier'],
                'inner_seed': study.best_trial.user_attrs['inner_seed'],
                'params': study.best_params,
                'trial': study.best_trial.number,
                'value': study.best_value,
            },
        }
    else:
        return {
            'n_trials': len(study.trials),
            'name': study.study_name,
            'id': study.study_id,
            'prediction_task': prediction_task,
            'start': study.user_attrs['Date'],
            'seed': study.user_attrs['Seed'],
            'best': {
                'accuracy': study.best_trial.user_attrs['accuracy'],
                'micro_f1': study.best_trial.user_attrs['micro_f1'],
                'macro_f1': study.best_trial.user_attrs['macro_f1'],
                'method': study.best_trial.user_attrs['method'],
                'classifier': study.best_trial.user_attrs['classifier'],
                'inner_seed': study.best_trial.user_attrs['inner_seed'],
                'params': study.best_params,
                'trial': study.best_trial.number,
                'value': study.best_value,
            },
        }


def create_graphs(*, input_path, training_path, testing_path, weighted):
    """Create the training/testing graphs needed for evalution."""
    if training_path and testing_path is not None:
        graph, graph_train, testing_pos_edges, train_graph_filename = pipeline.train_test_graph(
            input_path,
            training_path,
            testing_path,
            weighted=weighted,
        )
    else:
        graph, graph_train, testing_pos_edges, train_graph_filename = pipeline.split_train_test_graph(
            input_edgelist=input_path,
            weighted=weighted,
        )
    return graph, graph_train, testing_pos_edges, train_graph_filename


def do_evaluation(
    *,
    input_path,
    training_path: Optional[str] = None,
    testing_path: Optional[str] = None,
    method,
    prediction_task,
    dimensions: int = 300,
    number_walks: int = 8,
    walk_length: int = 8,
    window_size: int = 4,
    p: float = 1.5,
    q: float = 2.1,
    alpha: float = 0.1,
    beta: float = 4,
    epochs: int = 5,
    kstep: int = 4,
    order: int = 3,
    embeddings_path: Optional[str] = None,
    predictive_model_path: Optional[str] = None,
    training_model_path: Optional[str] = None,
    evaluation_file: Optional[str] = None,
    classifier_type: Optional[str] = None,
    weighted: bool = False,
    labels_file: Optional[str] = None,
):
    """Train and evaluate an NRL model."""
    if prediction_task == 'link_prediction':
        node_list = None
        labels = None
        graph, graph_train, testing_pos_edges, train_graph_filename = create_graphs(
            input_path=input_path,
            training_path=training_path,
            testing_path=testing_path,
            weighted=weighted,
        )
    else:
        if not labels_file:
            raise ValueError("No input label file. Exit.")
        node_list, labels = read_node_labels(labels_file)
        train_graph_filename = input_path
        graph, graph_train, testing_pos_edges = None, None, None

    model = embedding_training(
        train_graph_filename=train_graph_filename,
        method=method,
        dimensions=dimensions,
        number_walks=number_walks,
        walk_length=walk_length,
        window_size=window_size,
        p=p,
        q=q,
        alpha=alpha,
        beta=beta,
        epochs=epochs,
        kstep=kstep,
        order=order,
        weighted=weighted,
    )
    if training_model_path is not None:
        model.save_model(training_model_path)
    if embeddings_path is not None:
        model.save_embeddings(embeddings_path)
    if method == 'LINE':
        embeddings = model.get_embeddings_train()
    else:
        embeddings = model.get_embeddings()

    _results = dict(
        input=input_path,
        method=method,
        dimension=dimensions,
        user=getpass.getuser(),
        date=datetime.datetime.now().strftime('%Y-%m-%d-%H%M%S'),
    )
    if prediction_task == 'link_prediction':
        auc_roc, auc_pr, accuracy, f1, mcc = pipeline.do_link_prediction(
            embeddings=embeddings,
            original_graph=graph,
            train_graph=graph_train,
            test_pos_edges=testing_pos_edges,
            save_model=predictive_model_path,
            classifier_type=classifier_type,
        )
        _results['results'] = dict(
            auc_roc=auc_roc,
            auc_pr=auc_pr,
            accuracy=accuracy,
            f1=f1,
            mcc=mcc,
        )
    else:
        accuracy, macro_f1, micro_f1, mcc = pipeline.do_node_classification(
            embeddings=embeddings,
            node_list=node_list,
            labels=labels,
            save_model=predictive_model_path,
            classifier_type=classifier_type,
        )
        _results['results'] = dict(
            accuracy=accuracy,
            macro_f1=macro_f1,
            micro_f1=micro_f1,
            mcc=mcc,
        )
    if evaluation_file is not None:
        json.dump(_results, evaluation_file, sort_keys=True, indent=2)
    return _results


def do_optimization(
    *,
    method,
    input_path,
    training_path,
    testing_path,
    trials,
    dimensions_range,
    storage,
    name,
    output,
    prediction_task,
    labels_file,
    classifier_type,
    study_seed,
    weighted: bool = False,
):
    """Run optimization a specific method and graph."""
    np.random.seed(study_seed)
    random.seed(study_seed)

    if prediction_task == 'link_prediction':
        node_list, labels = None, None
        graph, graph_train, testing_pos_edges, train_graph_filename = create_graphs(
            input_path=input_path,
            training_path=training_path,
            testing_path=testing_path,
            weighted=weighted,
        )
    elif not labels_file:
        raise ValueError("No input label file. Exit.")
    else:
        node_list, labels = read_node_labels(labels_file)
        graph, graph_train, testing_pos_edges, train_graph_filename = None, None, None, input_path

    if method == 'HOPE':
        study = hope_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
            prediction_task=prediction_task,
            node_list=node_list,
            labels=labels,
            classifier_type=classifier_type,
            weighted=weighted,
            seed=study_seed,
        )

    elif method == 'DeepWalk':
        study = deepwalk_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            study_seed=study_seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
            prediction_task=prediction_task,
            node_list=node_list,
            labels=labels,
            classifier_type=classifier_type,
            weighted=weighted,
        )

    elif method == 'node2vec':
        study = node2vec_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            study_seed=study_seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
            prediction_task=prediction_task,
            node_list=node_list,
            labels=labels,
            classifier_type=classifier_type,
            weighted=weighted,
        )

    elif method == 'GraRep':
        study = grarep_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            study_seed=study_seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
            prediction_task=prediction_task,
            node_list=node_list,
            labels=labels,
            classifier_type=classifier_type,
            weighted=weighted,
        )

    elif method == 'SDNE':
        study = sdne_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            study_seed=study_seed,
            storage=storage,
            study_name=name,
            prediction_task=prediction_task,
            node_list=node_list,
            labels=labels,
            classifier_type=classifier_type,
            weighted=weighted,
        )

    else:
        study = line_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            study_seed=study_seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
            prediction_task=prediction_task,
            node_list=node_list,
            labels=labels,
            classifier_type=classifier_type,
            weighted=weighted,
        )

    study_json = study_to_json(study, prediction_task)
    json.dump(study_json, output, indent=2, sort_keys=True)


def train_model(
    *,
    input_path,
    method,
    dimensions: int = 300,
    number_walks: int = 8,
    walk_length: int = 8,
    window_size: int = 4,
    p: float = 1.5,
    q: float = 2.1,
    alpha: float = 0.1,
    beta: float = 4,
    epochs: int = 5,
    kstep: int = 4,
    order: int = 3,
    embeddings_path: Optional[str] = None,
    predictive_model_path: Optional[str] = None,
    training_model_path: Optional[str] = None,
    classifier_type: Optional[str] = None,
    weighted: bool = False,
    labels_file: Optional[str] = None,
    prediction_task,
):
    """Train a graph with an NRL model."""
    node_list, labels = None, None
    if prediction_task == 'node_classification':
        if not labels_file:
            raise ValueError("No input label file. Exit.")
        node_list, labels = read_node_labels(labels_file)
    model = embedding_training(
        train_graph_filename=input_path,
        method=method,
        dimensions=dimensions,
        number_walks=number_walks,
        walk_length=walk_length,
        window_size=window_size,
        p=p,
        q=q,
        alpha=alpha,
        beta=beta,
        epochs=epochs,
        kstep=kstep,
        order=order,
        weighted=weighted,
    )
    if training_model_path is not None:
        model.save_model(training_model_path)
    model.save_embeddings(embeddings_path)
    original_graph = nx.read_edgelist(input_path)
    if method == 'LINE':
        embeddings = model.get_embeddings_train()
    else:
        embeddings = model.get_embeddings()
    if prediction_task == 'link_prediction':
        pipeline.create_prediction_model(
            embeddings=embeddings,
            original_graph=original_graph,
            save_model=predictive_model_path,
            classifier_type=classifier_type,
        )
    else:
        pipeline.do_node_classification(
            embeddings=embeddings,
            node_list=node_list,
            labels=labels,
            classifier_type=classifier_type,
            save_model=predictive_model_path,
        )


def split_training_testing_sets(
    *,
    rebuild: bool = False,
    clustered_chemicals_file=DEFAULT_CLUSTERED_CHEMICALS,
    graph=DEFAULT_FULLGRAPH_PICKLE,
    g_train_path=DEFAULT_TRAINING_SET,
    g_test_path=DEFAULT_TESTING_SET,
    mapping_path=DEFAULT_MAPPING_PATH,
):
    """Split training and testing sets based on clustered chemicals."""
    # TODO: refractor and optimize
    if not rebuild and os.path.exists(DEFAULT_TRAINING_SET) and os.path.exists(DEFAULT_TESTING_SET):
        return nx.read_edgelist(DEFAULT_TRAINING_SET), nx.read_edgelist(DEFAULT_TESTING_SET)
    clustered_chemicals = pd.read_csv(clustered_chemicals_file, sep='\t', dtype={'PubchemID': str})
    cluster_dict = {
        row['PubchemID']: row['Cluster']
        for ind, row in clustered_chemicals.iterrows()
    }
    full_graph = pybel.from_pickle(graph)
    mapping_df = pd.read_csv(mapping_path, sep="\t", dtype={'node_id': str}, index_col=False)
    mapping_dict = {}
    for index, row in tqdm(mapping_df.iterrows(), desc='Reading mapping dataframe'):
        if row['namespace'] == 'pubchem.compound':
            mapping_dict[pybel.dsl.Abundance(namespace=row['namespace'], identifier=row['identifier'])] = row['node_id']
        elif row['namespace'] == 'umls':
            mapping_dict[pybel.dsl.Pathology(namespace=row['namespace'], name=row['name'])] = row['node_id']
        else:
            mapping_dict[pybel.dsl.Protein(namespace=row['namespace'], identifier=row['name'])] = row['node_id']
    df = []
    for source, target in tqdm(full_graph.edges(), desc='Creating splitting dataframe'):
        if source.identifier not in cluster_dict:
            df.append([mapping_dict[source], mapping_dict[target], 0.0])
        else:
            df.append([mapping_dict[source], mapping_dict[target], cluster_dict[source.identifier]])
    clustered_edgelist = pd.DataFrame(df, columns=['source', 'target', 'cluster'])
    train_inds, test_inds = next(GroupShuffleSplit(test_size=.20, n_splits=2, random_state=7).
                                 split(clustered_edgelist, groups=clustered_edgelist['cluster']))
    training = clustered_edgelist.iloc[train_inds]
    testing = clustered_edgelist.iloc[test_inds]
    g_train = nx.Graph()
    g_test = nx.Graph()
    for ind, row in tqdm(training.iterrows(), desc='Creating training set'):
        g_train.add_edge(row['source'], row['target'])
    for ind, row in tqdm(testing.iterrows(), desc='Creating testing set'):
        g_test.add_edge(row['source'], row['target'])

    for edge in tqdm(g_test.edges(), desc='Modifying training set'):
        if edge[0] not in g_train.nodes():
            g_train.add_node(edge[0])
            g_train.add_edge(edge[0], edge[1])
        if edge[1] not in g_train.nodes():
            g_train.add_node(edge[1])
            g_train.add_edge(edge[0], edge[1])
    for edge in tqdm(g_train.edges(), desc='Modifying testing set'):
        if g_test.has_edge(edge[0], edge[1]):
            g_test.remove_edge(edge[0], edge[1])
    nx.write_edgelist(g_train, g_train_path, data=False)
    nx.write_edgelist(g_test, g_test_path, data=False)
    return g_train, g_test


def repeat_experiment(
    *,
    input_path,
    training_path=None,
    testing_path=None,
    method,
    dimensions=300,
    number_walks=8,
    walk_length=8,
    window_size=4,
    p=1.5,
    q=2.1,
    alpha=0.1,
    beta=4,
    epochs=5,
    kstep=4,
    order=3,
    n=10,
    evaluation_file=None,
    weighted: bool = False,
):
    """Repeat an experiment several times."""
    all_results = {
        i: do_evaluation(
            input_path=input_path,
            training_path=training_path,
            testing_path=testing_path,
            method=method,
            dimensions=dimensions,
            number_walks=number_walks,
            walk_length=walk_length,
            window_size=window_size,
            p=p,
            q=q,
            alpha=alpha,
            beta=beta,
            epochs=epochs,
            kstep=kstep,
            order=order,
            embeddings_path=None,
            predictive_model_path=None,
            evaluation_file=None,
            weighted=weighted,
        )
        for i in tqdm(range(n), desc="Repeating experiment")
    }
    if evaluation_file is not None:
        json.dump(all_results, evaluation_file, sort_keys=True, indent=2)
    return all_results


def create_subgraph(
    *,
    fullgraph_path,
    source_name=None,
    source_identifier=None,
    source_type,
    target_name=None,
    target_identifier=None,
    target_type,
    weighted=False,
    mapping_path=DEFAULT_MAPPING_PATH,
):
    """Create subgraph."""
    fullgraph = pybel.from_pickle(fullgraph_path)
    for edge in fullgraph.edges():
        for iden, edge_d in fullgraph[edge[0]][edge[1]].items():
            fullgraph[edge[0]][edge[1]][iden]['weight'] = 1 - edge_d['weight']
    mapping_df = pd.read_csv(
        mapping_path,
        sep="\t",
        dtype={'identifier': str},
        index_col=False,
    ).dropna(axis=0, how='any', thresh=None, subset=None, inplace=False)
    mapping_dict = {}
    for ind, row in mapping_df.iterrows():
        if row['namespace'] != 'pubchem.compound':
            continue
        if row['name'] is None:
            continue
        mapping_dict[
            pybel.dsl.Abundance(namespace='pubchem.compound', identifier=row['identifier'])] = pybel.dsl.Abundance(
            namespace='pubchem.compound', name=row['name'])
    if source_type == 'chemical':
        source = pybel.dsl.Abundance(namespace='pubchem.compound', identifier=source_identifier)
    elif source_type == 'protein':
        source = pybel.dsl.Protein(namespace='uniprot', name=source_name, identifier=source_identifier)
    elif source_type == 'phenotype':
        source = pybel.dsl.Pathology(namespace='umls', name=source_name, identifier=source_identifier)
    else:
        raise Exception('Source type is not valid!')
    if target_type == 'chemical':
        target = pybel.dsl.Abundance(namespace='pubchem.compound', identifier=target_identifier)
    elif target_type == 'protein':
        target = pybel.dsl.Protein(namespace='uniprot', name=target_name, identifier=target_identifier)
    elif target_type == 'phenotype':
        target = pybel.dsl.Pathology(namespace='umls', name=target_name, identifier=target_identifier)
    else:
        raise Exception('Target type is not valid!')
    fullgraph_undirected = fullgraph.to_undirected()
    if weighted:
        paths = [p for p in nx.all_shortest_paths(fullgraph_undirected, source=source, target=target, weight='weight')]
    else:
        paths = [p for p in nx.all_shortest_paths(fullgraph_undirected, source=source, target=target)]
    subgraph_nodes = []
    if len(paths) > 100:
        for path in random.sample(paths, 10):
            for node in path:
                if node in subgraph_nodes:
                    continue
                subgraph_nodes.append(node)
    else:
        for path in paths:
            for node in path:
                if node in subgraph_nodes:
                    continue
                subgraph_nodes.append(node)
    subgraph = fullgraph.subgraph(subgraph_nodes)
    subgraph = nx.relabel_nodes(subgraph, mapping_dict)
    return subgraph
