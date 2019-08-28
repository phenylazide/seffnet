# -*- coding: utf-8 -*-

"""Utilities for ``se_kge``."""
import datetime
import getpass
import json
import os
from typing import Any, Mapping

import networkx as nx
import optuna
import pandas as pd
import pybel
from bionev import pipeline
from bionev.embed_train import embedding_training
from sklearn.model_selection import GroupShuffleSplit
from tqdm import tqdm

from .constants import (
    DEFAULT_CLUSTERED_CHEMICALS, DEFAULT_FULLGRAPH_PICKLE, DEFAULT_MAPPING_PATH, DEFAULT_TESTING_SET,
    DEFAULT_TRAINING_SET
)
from .optimization import (
    deepwalk_optimization, grarep_optimization, hope_optimization, line_optimization,
    node2vec_optimization, sdne_optimization,
)


def study_to_json(study: optuna.Study) -> Mapping[str, Any]:
    """Serialize a study to JSON."""
    return {
        'n_trials': len(study.trials),
        'name': study.study_name,
        'id': study.study_id,
        'start': study.user_attrs['Date'],
        'best': {
            'mcc': study.best_trial.user_attrs['mcc'],
            'accuracy': study.best_trial.user_attrs['accuracy'],
            'auc_roc': study.best_trial.user_attrs['auc_roc'],
            'auc_pr': study.best_trial.user_attrs['auc_pr'],
            'f1': study.best_trial.user_attrs['f1'],
            'method': study.best_trial.user_attrs['method'],
            'params': study.best_params,
            'trial': study.best_trial.number,
            'value': study.best_value,
        },
    }


def create_graphs(*, input_path, training_path, testing_path, seed):
    """Create the training/testing graphs needed for evalution."""
    if training_path and testing_path is not None:
        graph, graph_train, testing_pos_edges, train_graph_filename = pipeline.train_test_graph(
            input_path,
            training_path,
            testing_path,
        )
    else:
        graph, graph_train, testing_pos_edges, train_graph_filename = pipeline.split_train_test_graph(
            input_path,
            seed
        )
    return graph, graph_train, testing_pos_edges, train_graph_filename


def do_evaluation(
        *,
        input_path,
        training_path,
        testing_path,
        method,
        dimensions,
        number_walks,
        walk_length,
        window_size,
        p,
        q,
        alpha,
        beta,
        epochs,
        kstep,
        order,
        seed,
        embeddings_path,
        model_path,
        evaluation_file
):
    """Train and evaluate an NRL model."""
    graph, graph_train, testing_pos_edges, train_graph_filename = create_graphs(
        input_path=input_path,
        training_path=training_path,
        testing_path=testing_path,
        seed=seed,
    )
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
        seed=seed,
    )
    model.save_embeddings(embeddings_path)
    auc_roc, auc_pr, accuracy, f1, mcc = pipeline.do_link_prediction(
        embeddings=model.get_embeddings(),
        original_graph=graph,
        train_graph=graph_train,
        test_pos_edges=testing_pos_edges,
        seed=seed,
        save_model=model_path
    )
    _results = dict(
        input=input_path,
        method=method,
        dimension=dimensions,
        user=getpass.getuser(),
        date=datetime.datetime.now().strftime('%Y-%m-%d-%H%M%S'),
        seed=seed,
    )
    _results['results'] = dict(
        auc_roc=auc_roc,
        auc_pr=auc_pr,
        accuracy=accuracy,
        f1=f1,
        mcc=mcc,
    )
    json.dump(_results, evaluation_file, sort_keys=True, indent=2)
    return _results


def do_optimization(
        *,
        method,
        input_path,
        training_path,
        testing_path,
        trials,
        seed,
        dimensions_range,
        storage,
        name,
        output,
):
    """Run optimization a specific method and graph."""
    graph, graph_train, testing_pos_edges, train_graph_filename = create_graphs(
        input_path=input_path,
        training_path=training_path,
        testing_path=testing_path,
        seed=seed,
    )
    if method == 'HOPE':
        study = hope_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            seed=seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
        )

    elif method == 'DeepWalk':
        study = deepwalk_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            seed=seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
        )

    elif method == 'node2vec':
        study = node2vec_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            seed=seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
        )

    elif method == 'GraRep':
        study = grarep_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            seed=seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
        )

    elif method == 'SDNE':
        study = sdne_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            seed=seed,
            storage=storage,
            study_name=name,
        )

    else:
        study = line_optimization(
            graph=graph,
            graph_train=graph_train,
            testing_pos_edges=testing_pos_edges,
            train_graph_filename=train_graph_filename,
            trial_number=trials,
            seed=seed,
            dimensions_range=dimensions_range,
            storage=storage,
            study_name=name,
        )

    study_json = study_to_json(study)
    json.dump(study_json, output, indent=2, sort_keys=True)


def train_model(
        *,
        input_path,
        method,
        dimensions,
        number_walks,
        walk_length,
        window_size,
        p,
        q,
        alpha,
        beta,
        epochs,
        kstep,
        order,
        seed,
        model_path,
        embeddings_path,
):
    """Train a graph with an NRL model."""
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
        seed=seed,
    )
    model.save_embeddings(embeddings_path)
    original_graph = nx.read_edgelist(input_path)
    pipeline.create_prediction_model(
        embeddings=model.get_embeddings(),
        original_graph=original_graph,
        seed=seed,
        save_model=model_path
    )


def split_training_testing_sets(
        *,
        rebuild: bool = False,
        clustered_chemicals_file=DEFAULT_CLUSTERED_CHEMICALS,
        graph=DEFAULT_FULLGRAPH_PICKLE,
        g_train_path=DEFAULT_TRAINING_SET,
        g_test_path=DEFAULT_TESTING_SET,
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
    mapping_df = pd.read_csv(DEFAULT_MAPPING_PATH, sep="\t", dtype={'node_id': str}, index_col=False)
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
